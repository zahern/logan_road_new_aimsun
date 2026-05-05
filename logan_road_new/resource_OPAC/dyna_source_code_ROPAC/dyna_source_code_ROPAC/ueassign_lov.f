      subroutine ueassign_lov
c --
      use muc_mod

	integer  dy_muc,error,ipathsize,iflag3,ip,maxnu_pa
	integer,allocatable::testpath(:)
	integer,allocatable::tmpuepath(:) 
	integer t,tmpnodsum,icheck,iflag2,mm,i,j,mk
	real,allocatable::aux(:)
      real,allocatable::auxprob(:)
      real newprob
		
	dy_muc=3

	open(file='RPUELOV.dat',unit=58,status='unknown') 

c --
c -- This subroutine read paths from TD_KSP and compared with the existing
c -- paths, if not found the same paths, construct the linked list for
c -- this new paths into uepath(:,:,:,:)
c -- These paths are stored as Linked-List data structure to conserve memory
c -- MucPath_lov(noofnodes,noof_master_destinations,soint,10) stores the initial 
c -- address for the linked-list ue path, same as uepath()
c -- traverse is the pointer for forwarding the linked list
c --
c -- This subroutine is called from the main program rhmuc_main
c --
c -- This calls any other subroutines.
c --
c -- INPUT
c -- None
c --
c -- OUTPUT
	maxnu_pa=1000
c	print *,'AlexUE01'
      allocate(aux(itedex+1),stat=error)
	if(error.ne.0)then
	  write(911,*)"allocate aux error - insufficient memory"
	  stop
	endif
      
	allocate(auxprob(itedex+1),stat=error)
      if(error.ne.0)then
        write(911,*) "allocate auxprob error - insufficient memory"
        stop
      endif
      auxprob(:)=0.0
      aux(:) = 0.0
      ueaccuprob_lov(:,:,:,:)=0.0
	
      allocate(testpath(maxnu_pa),stat=error)
	if(error.ne.0)then
	  write(911,*)"allocate testpath error - insufficient memory"
	  stop
	endif
      testpath(:)=0
	
      allocate(tmpuepath(maxnu_pa),stat=error)
    	if(error.ne.0)then
	  write(911,*)"allocate tmpuepath error - insufficient memory"
	  stop
	endif
      tmpuepath(:)=0
c	print *,'AlexUE02',nzones,noof_master_destinations_original,
c     + soint
!      do 100 j = 1, noof_master_destinations
      do 100 j=1,noof_master_destinations_original
!	write(58,*) 'Destination',j

	real_SuperzoneIndex=j
c	print *,'AlexUE02001'
      call kspcost_main(dy_muc)
c	print *,'AlexUE02002'
      do 10 t=1,soint
!	write(58,*) 'Time',t
!     End of change

! change from noofnodes to nzones (centroid)
!      do 200 i = 1,noofnodes_org
      do 200 i=1,nzones

!	write(58,*) '---------'
	
	do 800 kp=1,1
	  aux(kp)=0.0
	  tmpnodsum=0
!       ifrom = i 
	  ifrom=origin(i)
!       ito = j
        ito=1
! End of change 
        ict=ifix(float(t-1)*tad/ftr)+1
c  -- 
        mov=BackPointr(ifrom+1)-BackPointr(ifrom)+1
!	  gen_cost_min=20000
	  gen_cost_min=2000000

        do iiu=1,no_link_type
           do kk=1,kay
           generalized_cost=labeloutCost(iiu,1,
     *                           ito,ifrom,ict,kk,mov)

           if(generalized_cost.LT.gen_cost_min)then
               gen_cost_min=Generalized_cost
               ii_ours=iiu
               kk_ours=kk
           endif
           enddo
         enddo

c	print *,'AlexUE0201'
! It seems that this condition is satisfied when there is no path between ifrom and ito
         if(gen_cost_min.gt.PenForPreventMove)then
      
	if(PathPointerOut1(ii_ours, 1, ito, ifrom, ict, kk_ours, nu_mv)
     +.ne.0) then
	  print *, 'Warning! path contains prevented movement'
!	elseif
!	  print *, 'ue ifrom = ', nodenum(ifrom), 'ito = ', nodenum(ito)
	endif
! end of modification
	   endif
c          know=labelpointerout(ii_ours,1,ito,ifrom,ict,kk_ours,mov)
         know=kk_ours

         if(know.eq.0) know=1
	   iniknow=know
	   inimov=mov
c --		       
         k=1
c --
c	print *,'AlexUE021'
c --
         do 20 while(ifrom.ne.destination(real_SuperzoneIndex).and.
     *   k.le.maxnu_pa)

!            if(connectivity(ifrom,real_SuperzoneIndex).lt.1) go to 800
  	  
	       tmpuepath(k)=ifrom
	       tmpnodsum=tmpnodsum+ifrom
             k=k+1
             ifromtmp=ifrom
             ktemp=know
             movetemp=mov
             icttemp=ict

         ict=pathpointerout4(ii_ours,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         mov=pathpointerout3(ii_ours,1,ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know=pathpointerout2(ii_ours,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(ii_ours,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)

c --  If dead connectivity from any intermediate node, skip this path
          if(k.ge.maxnu_pa.or.
     *	 ict.eq.0.or.mov.eq.0.or.know.eq.0.or.ifrom.eq.0) then
           write(911,*) 'in UE assignment'
           write(911,'("origin",i4," destination",i4," time",i4)') i,j,t
           write(911,*) 'exceeded the parameter maxnu_pa'
           write(911,'(20i4)') tmpuepath(1:maxnu_pa)
           icheck = 1
           goto 800
          endif 
20       continue
c --  assign the destination
      tmpnodsum=tmpnodsum+ifrom
      tmpuepath(k)=ifrom
      tmpuepath(k+1:maxnu_pa)=0
c --  check cycle
	nnk=k
	ifg2=0
455   continue

c	print *,'AlexUE03'

!      do ml=3,nnk
!       do kk=1,ml-1
        do ml=6,nnk
           do kk=4,ml-1

              if(tmpuepath(kk).eq.tmpuepath(ml))then
			ifg2=1
			idiff=ml-kk
			nnk=nnk-idiff
			do jd=kk,nnk
				tmpuepath(jd)=tmpuepath(jd+idiff)
			enddo
			do mm=nnk+1,maxnu_pa
			tmpuepath(mm)=0
			enddo
			goto 455
			endif
		 enddo
	  enddo
c  -- update sumynp
        if(ifg2.gt.0)then
		tmpnodsum=0
		if(nnk.lt.1) print *, 'ueassign, nnk=',nnk
		do ii=1,nnk
			tmpnodsum=tmpnodsum+tmpuepath(ii)
		enddo
        endif

c --  check if this path exists for this i,j,t
	  iflag2=0
	  icheck=1
	  do icheck=1,NumUePath_lov(i,j,t)
	  if(tmpnodsum.gt.0.and.uepolicy_lov(i,j,t,icheck)%nodesum
     +       .eq.tmpnodsum)then
	     iflag2=icheck
	  endif
	  enddo

c 	if(i.eq.6.and.j.eq.4.and.t.eq.1) print *,'Alexif',iflag2,
c     +NumUePath_lov(i,j,t),uepath_lov(i,j,t,1),uepath_lov(i,j,t,2)

c --  determined the number of paths for this i,j,t
	IF(iflag2.eq.0)THEN !new path found for this i,j,t

        NumUePath_lov(i,j,t)=NumUePath_lov(i,j,t)+1
	  nowpath=NumUePath_lov(i,j,t)

c --  check if this path exists in the grand path set MucPath()
c --  if so, update the grand path set

        iflag3=0
        do ip=1,NumMucPath_lov(i,j)
	  if(tmpnodsum.eq.MucPathAtt_lov(i,j,ip)%node_sum) iflag3=ip
	  enddo

	  if(iflag3.eq.0)then  !new path found, put in grand path set
	    NumMucPath_lov(i,j)=NumMucPath_lov(i,j)+1

          if(NumMucPath_lov(i,j).ge.muc_path_total_lov)then
	    print *, 'origin:', i, '  destination:', j
	    call MUCArray_Reallocate(1) 
          endif
! End of modification

	    MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_sum=tmpnodsum
	    MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_number=nnk

!	  traverse=>MucPath_lov(i,j,NumMucPath_lov(i,j))
!	  ipath = 1
!	  do while (tmpuepath(ipath).gt.0) !assign nodes into linked list
!           allocate(traverse%next_node,stat=error)
!            traverse%node = tmpuepath(ipath)
!            traverse=>traverse%next_node
!            ipath = ipath + 1
!	  enddo
!	  nullify(traverse%next_node)

c	print *,'AlexUE04'
c	DEALLOCATE(MUCPath_Lov_Array(iz,iy,ix)%P,stat=error)

	if(associated(MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P))then
	deallocate(MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P,
     +stat=error)
	  if(error.ne.0)then
	    write(911,*)"deallocate MUCPath_Lov_Array%P vector error"
	    print *,"deallocate MUCPath_Lov_Array%P vector error"
	    pause
	  endif
      endif

c	print *,'AlexUE03'

	ALLOCATE(MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(nnk),
     +stat=error)
	if(error.ne.0)then
      write(911,*)"allocate P() in mucpath_lov_array vector, error"
	  pause
	endif

c	print *,'AlexUE04'
   
	! Copy contents from temp back to array 
	  ipath=1
	  do while(tmpuepath(ipath).gt.0)
		MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(ipath)
     +	   =tmpuepath(ipath)

		if(ipath.gt.nnk)then
          print *, ipath,nnk
	  	iidebug=1
		endif

		if(tmpuepath(ipath).eq.0)then
          print *, ipath, tmpuepath(ipath)
	  	iidebug=1
		endif

		ipath=ipath+1
	  enddo
        
		if(ipath-1.ne.nnk)then
	print *, 'Inconsistency exists between the numbers of nodes for
     +	  MUC paths'
		pause
		endif

! End of Modification
	  
		uepath_lov(i,j,t,nowpath)=NumMucPath_lov(i,j)
		uepolicy_lov(i,j,t,nowpath)%nodesum=tmpnodsum !record node sum for this new path
		uepolicy_lov(i,j,t,nowpath)%nodenumber=nnk
	 
	    else	! this path is found the grand path set
	    uepath_lov(i,j,t,nowpath)=iflag3
          uepolicy_lov(i,j,t,nowpath)%nodesum= 
     +        MucPathAtt_lov(i,j,iflag3)%node_sum !record node sum for this new path
          uepolicy_lov(i,j,t,nowpath)%nodenumber=
     +        MucPathAtt_lov(i,j,iflag3)%node_number 
	    endif

c	if(i.eq.6.and.j.eq.4.and.t.eq.1) print *,'Alexnow',nowpath

c	if(uepath_lov(i,j,t,nowpath).lt.1)
c     +print *,'AlexUE04a',uepath_lov(i,j,t,nowpath)

c	if(uepath_lov(i,j,t,2).lt.1)
c     +print *,'AlexUE04b',i,j,t,uepath_lov(i,j,t,2)

      ELSE
	  nowpath=NumUePath_lov(i,j,t)
	ENDIF
  	 
c --------------------------------
c --  Starting the assignment
c --------------------------------

c	print *,'AlexUE05'

      IF(iflag2.eq.0)then !new path found

       do kh=1,nowpath
		if (kh.ne.nowpath)then
			aux(kh)=0.0
			auxprob(kh)=0.0     
		else
			aux(kh)=real(uenxz_lov(i,j,t))  ! all trips go to the aux path of the new path
			auxprob(kh)=1.0         
		endif
  	 enddo
	 do mb=1,nowpath
	  xn=(1.0-1.0/(iteration+1))*
     *  uepolicy_lov(i,j,t,mb)%NumOfVehicle
     *  +1.0/(iteration+1)*aux(mb)
	  if(abs(xn-uepolicy_lov(i,j,t,mb)%NumOfVehicle).gt.muc_diff)
     *  TotalViolation=TotalViolation+ 
     *  abs(xn-uepolicy_lov(i,j,t,mb)%NumOfVehicle)
	  uepolicy_lov(i,j,t,mb)%NumOfVehicle=xn
        newprob=(1.0-1.0/(iteration+1))*   
     *  uepolicy_lov(i,j,t,mb)%prob+1.0/(iteration+1)*auxprob(mb)
        uepolicy_lov(i,j,t,mb)%prob=newprob
	 enddo

      ELSE                 ! old path found
	
       do kh=1,nowpath
	  if(kh.ne.iflag2)then
	   aux(kh)=0.0
	   auxprob(kh)=0.0
        else
	   aux(kh)=real(uenxz_lov(i,j,t))  ! all trips go to aux path of found path
         auxprob(kh)=1.0    
	  endif
  	 enddo
	 do mb=1,nowpath
	  xn=(1.0-1.0/(iteration+1))*
     *  uepolicy_lov(i,j,t,mb)%NumOfVehicle
     *  +1.0/(iteration+1)*aux(mb)
	  if(abs(xn-uepolicy_lov(i,j,t,mb)%NumOfVehicle).gt.muc_diff)
     *  TotalViolation=TotalViolation+ 
     *  abs(xn-uepolicy_lov(i,j,t,mb)%NumOfVehicle)
	  uepolicy_lov(i,j,t,mb)%NumOfVehicle=xn
        newprob=(1.0-1.0/(iteration+1))* 
     *  uepolicy_lov(i,j,t,mb)%prob+1.0/(iteration+1)*auxprob(mb)
        uepolicy_lov(i,j,t,mb)%prob=newprob
 	  enddo
	ENDIF

800   continue      
70	continue
c ---------------------------------------------------
c -----  calculate accumulated prob for each i,j,t,k
c ---------------------------------------------------

      do kk=1,nowpath
       if(kk.eq.1)then  ! the first path
         ueaccuprob_lov(i,j,t,kk)=uepolicy_lov(i,j,t,kk)%prob
       else
         ueaccuprob_lov(i,j,t,kk)=ueaccuprob_lov(i,j,t,kk-1)+
     *   uepolicy_lov(i,j,t,kk)%prob
       endif
       if(kk.eq.nowpath) ueaccuprob_lov(i,j,t,kk)=1.0
      enddo
	

1001    format(2i6,f8.4,i6)
1002    format(150i7)
200   continue
10    continue
100   continue

c	print *,'AlexUE06',uepath_lov(6,4,1,2)

c	pause
      
c ------------------------------------
c     reassign paths to UE vehicles
c     has been moved to get_uepath_lov
c ------------------------------------

c	print *,'AlexUE07'

      do t=1,soint
        if(t.eq.2) write(58,*) 'Time',t
c		print *,'AlexUE071'
        do j=1,noof_master_destinations_original
          if(t.eq.2) write(58,*) 'Destination',j


!      do i = 1,noofnodes_org
c	print *,'AlexUE072'
	 do i=1,nzones
c	write(58,*) '---------'

c ----------------------------------------------------
c -----  small test to see if the path is correct
c ----------------------------------------------------
 
        if(t.eq.2) write(58,*) i,NumUePath_lov(i,j,t),uenxz_lov(i,j,t)
c		print *,'AlexUE073'
		do mk=1,NumUePath_lov(i,j,t)
!       traverse=>MucPath_lov(i,j,uepath_lov(i,j,t,mk))
       ih=1
       testpath(:)=0
!       do while (associated(traverse%next_node))
!        testpath(ih) = traverse%node
!        traverse=>traverse%next_node
!        if(ih.lt.maxnu_pa) then
!          ih=ih+1
!        else
!          print *, 'Eror in ueassign, path longer than maxnu_pa'
!          write(*,*) (testpath(mh),mh=1,maxnu_pa)
!          exit
!        endif
!       enddo
c 	print *,'AlexUE074'
      do ih=1,MucPathAtt_Lov(i,j,uepath_lov(i,j,t,mk))%node_number

      testpath(ih)=MUCPath_Lov_Array(i,j,uepath_lov(i,j,t,mk))%P(ih)

	  if(testpath(ih).eq.0)then
	      print *, ih, testpath(ih) 
	  	iidebug=1
	  endif

        if(ih.gt.maxnu_pa)then
          print *, 'Eror in ueassign, path longer than maxnu_pa'
          write(*,*) (testpath(mh),mh=1,maxnu_pa)
          exit
        endif

      enddo

	 ipathsize=MucPathAtt_Lov(i,j,uepath_lov(i,j,t,mk))%node_number	
!End of modification
c	print *,'AlexUE075',i,j,t,mk,uepath_lov(i,j,t,mk)
***************************
        do mm2=2,ipathsize-1
        if(testpath(mm2).gt.noofnodes_org.or.testpath(mm2).lt.1)then
        print *, 'error in testpath'
        endif
        enddo
c	print *,'AlexUE0751'
******************************

!       write(58,1001) uepolicy_lov(i,j,t,mk)%NumOfVehicle,

        if(t.eq.2) write(58,1001) nodenum(testpath(2)),uepolicy_lov
     * (i,j,t,mk)%NumOfVehicle,uepolicy_lov(i,j,t,mk)%prob,ipathsize-2
	 
c 	print *,'AlexUE0752'

!       write(58,1002) uepolicy_lov(i,j,t,mk)%nodenumber-1,! not printing centroid
!     *  nodenum(testpath(1:ih-2))

c 	print *,'AlexUE0752a',ipathsize-2,NumUePath_lov(i,j,t)

        if(t.eq.2) write(58,1002) nodenum(testpath(2:ipathsize-1))		! not printing centroid
c	print *,'AlexUE076'

      enddo
      enddo
      enddo
      enddo

c	print *,'AlexUE08'

      deallocate(aux,stat=error)
      if(error.ne.0)then
         print *,"deallocate aux error"
         stop
      endif
      deallocate(auxprob,stat=error)
          if(error.ne.0)then
           print *,"deallocate auxprob error"
           stop
          endif
      deallocate(testpath,stat=error)
      deallocate(tmpuepath,stat=error)

      close(58)
      return
      end
