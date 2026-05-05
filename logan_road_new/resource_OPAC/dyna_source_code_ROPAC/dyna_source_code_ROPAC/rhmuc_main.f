      program rhmucmain
c --	
      use muc_mod
      use vector_mod
      use LinkList_mod
      integer::dy_muc=0
      integer,save::MaxIntervals=0
      integer error

	TotalViolation=29000
      open(unit=1,file='matrix.dat',STATUS='UNKNOWN')	
	! We only need to initial muc_path_total_lov once

      muc_path_total_lov=10
      muc_path_total_hov=10
  
      call openfile

      open(file='testPath.dat',unit=119,status='unknown',iostat=error)
	if(error.ne.0)then
         write(911,*) 'Error when opening testPath.dat'
	   stop
	endif
	! End of Modification

c  -- initialize counters 
	! itedex = number of user specified iterations
   
      read(95,*) stagelength
      read(95,*) itedex,realdm
      read(95,*) ftr,tad,muc_diff,no_via

      iteration = 0
      maxtime = 0
      aggint = 0
      soint = 0
      numof_siminterval = 0
	! End

c  --- ----------------------------------  
c          call input()

      call dynasmart(MaxIntervals) 

c  --------------------------------------

	open(file='RPSOLOV.dat',unit=58,status='REPLACE',action='write') 
	close(58)
	open(file='RPSOHOV.dat',unit=59,status='REPLACE',action='write') 
	close(59)
	open(file='RPUELOV.dat',unit=58,status='REPLACE',action='write') 
	close(58)
	open(file='RPUEHOV.dat',unit=59,status='REPLACE',action='write') 
	close(59)

      best_iteration=-1
	best_MOE=99999999.0
	current_MOE=-1.0
c	! end
c     Enetering MUC procedures

      do while(iteration.lt.itedex.and.
     * ((iso_ok.eq.1.or.iue_ok.eq.1).and.TotalViolation.gt.no_via))
 
      TotalViolation=0.0
      iteration=iteration+1
      dy_muc=1    !muc mode

c  -- pre-process
!      do j = 1,jj
!	  if(vehclass(j).eq.2.or.vehclass(j).eq.3) call VhcATT_Clear(j,1)
!	enddo 

c --  redefine iti_nu as number of aggregation intervals per stagelength
c --  this will be used in allocating memory and ksp subroutines
      iti_nu=ifix(float(maxintervals)/ftr)+1

c  -- call allocate_ksp "again" to allocate TD for ksp
c	print *, 'Alex1200'
      call allocate_ksp(dy_muc)

      if(muc_veh(3).gt.0) then !if UE vehicles exist
c - TD-KSP
		penaltyMG(:,:,:)=0
	    print *, "UE-KSP ..."
	    dy_muc = 3

!	    call kspcost_main(dy_muc)

!           if(muc_veh(2).lt.0.0001) then
!		    call deallocate_ksp1 ! if no so vehicle
!	     endif
		 print *, "UE_lov assignment ..."
           call ueassign_lov
		 print *, "UE_lov assignment OK"
!           if(total_hov.gt.0.00001) then
           if(Veh_Type(3).eq.1) then
 	     print *, "UE_hov assignment ..."
           call ueassign_hov
           endif
c	Print *,'Alex01'
! Because we already calculate KSP in ueassign_lov, we can deallocate_ksp1 here
           if(muc_veh(2).lt.0.0001) then
		 call deallocate_ksp1  ! if no so vehicle
	     endif
c	Print *,'Alex02'
           if(muc_veh(2).lt.0.0001) then
		 call deallocate_ksp2
	   endif
      endif
c	Print *,'Alex03'
      if(muc_veh(2).gt.0)then      ! if so vehicle found
	     print *, "marginal..."
c -- the SO does not have cost with it, only the marginals.
	     cost(:,:,:)=0

! Calculate link so marginals for eacn sim interval and then aggregate for each agg interval
!		 call somarginal
           call somarginal_siminterval
! End
		print *, "SO-KSP..."
	     dy_muc = 2

!	     call kspcost_main(dy_muc)
!          call deallocate_ksp1
! End
	     print *, "SO_lov assignment ..."
           call soassign_lov
!           if(total_hov.gt.0.00001) then
            if(Veh_Type(3).eq. 1) then
           print *, "SO_hov assignment ..."
           call soassign_hov
           endif

! Because we already calculate KSP in soassign_lov, we can deallocate_ksp1 here
		call deallocate_ksp1
		call deallocate_ksp2
      endif

      if(iteration.gt.0) then
	write(180,*) ""
	write(180,*) ""
	write(180,*) "------"
      write(180,*) 'TotalViolation=',TotalViolation
      print *, 'TotalViolation=',TotalViolation
	write(180,*) "------"
	write(180,*) ""
	write(180,*) ""
	endif

c --  re-process vehicle attributes
      do j = 1, jj
         icurrnt(j)=1
	
	! modified by MTI to have UE and SO vehicles starting at downstream node of the 
	! connector links to consistently compare 1 shot with MUC mode

		if(vehclass(j).eq.2.or.vehclass(j).eq.3)then 
            xpar(j)=0
		endif

      enddo

      call closefile

      call openfile

      jtotal = jj

      dy_muc = 0
!      call allocate_ksp(dy_muc)
      call dynasmart(maxintervals)

c	print *, 'Alex1200'	  
c ----------------------------------
      enddo
c --  End of MUC loop
c ----------------------------------
c      if(realdm.ne.1) call write_link_tt

c	print *, 'Alex1300'
	
      call closefile

      close(119)	
! End	
c	print *, 'Alex1400'
!      pause
      if(iso_ok.eq.1.or.iue_ok.eq.1)then
        call deallocate_muc
      endif
! output actual simulation periods
      open(unit=9999,file='SimPeriod.opt',status="unknown")
	write(9999,'(f8.1)') MaxIntervals*tii
	close(9999)
c	print *, 'Alex1500'
      call deallocate_dyna2
      close(1)
	print *, 'DYNASMART-P finished'
	pause
      end
