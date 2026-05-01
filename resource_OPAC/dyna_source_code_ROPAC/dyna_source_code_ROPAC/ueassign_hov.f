      subroutine  ueassign_hov

      use muc_mod
      integer maxnu_pa,error

	integer  dy_muc
	
	integer,allocatable:: testpath(:)
	integer,allocatable:: tmpuepath(:)
	integer t,tmpnodsum,icheck,iflag2,mm
	real,allocatable::aux(:)
      real,allocatable::auxprob(:)
      real newprob
	open(file='RPUEHOV.dat',unit=59,status='unknown',action='write') 

c --
c -- This subroutine read paths from TD_KSP and compared with the existing
c -- paths, if not found the same paths, construct the linked list for
c -- this new paths into ueath(:,:,:,:)
c -- These paths are stored as Linked-List data structure to conserve memory
c -- MucPath_hov(noofnodes,noof_master_destinations,soint,10) stores the initial 
c -- address for the linked-list ue path, same as uepath()
c -- traverse is the pointer for forwarding the linked list
c --
c -- This subroutine is called from the main program rhmuc_main
c --
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT
c -- None

c --
c -- OUTPUT


	dy_muc = 3

	maxnu_pa = 1000
      allocate(aux(itedex+1),stat=error)
	  if(error.ne.0) then
	    print *,"allocate aux error"
	    stop
	  endif
      allocate(auxprob(itedex+1),stat=error)
          if(error.ne.0) then
            print *,"allocate aux error"
            stop
          endif
      auxprob(:) = 0.0
      aux(:) = 0.0
      ueaccuprob_hov(:,:,:,:) = 0.0
	allocate(testpath(maxnu_pa),stat=error)
	 testpath(:) = 0
	allocate(tmpuepath(maxnu_pa),stat=error)
    	 tmpuepath(:) = 0


!     do 100 j = 1, noof_master_destinations
	do 100 j = 1, noof_master_destinations_original
!	write(59,*) 'Destination',j


	real_SuperzoneIndex = j
	! We don't need to re-calculate the KSP in the HOV part,
	! since we already get KSP for both LOV and HOV in the LOV part

!      !call kspcost_main(dy_muc)
        call kspcost_main(dy_muc)

	do 10 t = 1, soint
!	write(59,*) 'Time',t
! End


!      do 200 i = 1,noofnodes_org
      do 200 i = 1,nzones
!	write(59,*) '---------'
	
	do 800 kp = 1, 1
	 aux(kp) = 0.0
	 tmpnodsum = 0




!	 ifrom = i
	 ifrom = origin(i)

!       ito = j    

       ito = 1
! End of change
   
       ict = ifix(float(t-1)*tad/ftr)+1
c  -- 

        mov=BackPointr(ifrom+1)-BackPointr(ifrom)+1


!	  gen_cost_min=20000
	  gen_cost_min=2000000
        do iiu=1,no_link_type
           do kk=1,kay
           generalized_cost=labeloutCost(iiu,2,
     *                           ito,ifrom,ict,kk,mov)

           if(generalized_cost.LT.gen_cost_min) then
               gen_cost_min=Generalized_cost
               ii_ours = iiu
               kk_ours = kk
           endif
           enddo
         enddo


c          know=labelpointerout(ii_ours,2,ito,ifrom,ict,kk_ours,mov)
           know = kk_ours


           if (know.eq.0) know = 1
           iniknow = know
	     inimov = mov

c --		           
            k=1
c --
c --

        do 20 while(ifrom.ne.destination(real_SuperzoneIndex).and.
     * k.le.maxnu_pa)


!            if(connectivity(ifrom,real_SuperzoneIndex).lt.1) go to 800
  	  
	       tmpuepath(k) = ifrom
	       tmpnodsum = tmpnodsum + ifrom
             k=k+1
             ifromtmp=ifrom
             ktemp=know
             movetemp=mov
             icttemp=ict

	
         ict=  pathpointerout4(ii_ours,2,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         mov=  pathpointerout3(ii_ours,2,ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know= pathpointerout2(ii_ours,2,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(ii_ours,2,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)

c --  If dead connectivity from any intermediate node, skip this path
             if(k.ge.maxnu_pa.or.
     *	   ict.eq.0.or.mov.eq.0.or.know.eq.0.or.ifrom.eq.0) then
               write(911,*) 'in UE assignment'
               write(911,*) 'origin',i,'destination',j,'time',t
               write(911,*) 'exceeded the parameter maxnu_pa'
               write(911,'(20i4)') tmpuepath(1:maxnu_pa)
               icheck = 1
               stop
			 go to 800

             endif 
20      continue
c --  assign the destination
      tmpnodsum = tmpnodsum + ifrom
      tmpuepath(k) = ifrom
      tmpuepath(k+1:maxnu_pa) = 0
c --  check cycle
	nnk = k
	ifg2 = 0
455   continue


!      do ml=3,nnk
!       do kk=1,ml-1
       do ml=6,nnk
       do kk=4,ml-1

       if(tmpuepath(kk).eq.tmpuepath(ml)) then
        ifg2 = 1
        idiff=ml-kk
        nnk=nnk-idiff
        do jd=kk,nnk
         tmpuepath(jd)=tmpuepath(jd+idiff)
        enddo
        do mm=nnk+1,maxnu_pa
         tmpuepath(mm)=0
        enddo
        go to 455
       endif
       enddo
	enddo
c  -- update sumynp
      if(ifg2.gt.0) then
        tmpnodsum= 0
        if(nnk.lt.1) print *, 'ueassign, nnk=',nnk
       do ii = 1, nnk
        tmpnodsum = tmpnodsum + tmpuepath(ii)
       enddo
      endif


c --  check if this path exists for this i,j,t
	iflag2 = 0
	icheck = 1
	do icheck = 1, NumUePath_hov(i,j,t)
	  if(tmpnodsum.gt.0.and.uepolicy_hov(i,j,t,icheck)%nodesum
     +       .eq.tmpnodsum) then
	     iflag2 = icheck
	  endif
	enddo

c --  determined the number of paths for this i,j,t
	IF(iflag2.eq.0) then !new path found for this i,j,t

       NumUePath_hov(i,j,t)=NumUePath_hov(i,j,t) + 1
	 nowpath=NumUePath_hov(i,j,t)

c --  check if this path exists in the grand path set MucPath()
c --  if so, update the grand path set
       iflag3 = 0
       do ip = 1, NumMucPath_hov(i,j)
	 if(tmpnodsum.eq.MucPathAtt_hov(i,j,ip)%node_sum) iflag3 = ip
	 enddo
	 if(iflag3.eq.0) then  !new path found, put in grand path set
	  NumMucPath_hov(i,j)=NumMucPath_hov(i,j)+1


        if(NumMucPath_hov(i,j) .ge. muc_path_total_hov) then
!	    print *, 'origin:', i, '  destination:', j
	    call MUCArray_Reallocate(2) 
        endif
! End of modification

	  MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum = tmpnodsum
	  MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number = nnk
!	  traverse=>MucPath_hov(i,j,NumMucPath_hov(i,j))
!	  ipath = 1
!	  do while (tmpuepath(ipath).gt.0) !assign nodes into linked list
!           allocate(traverse%next_node,stat=error)
!            traverse%node = tmpuepath(ipath)
!            traverse=>traverse%next_node
!            ipath = ipath + 1
!	  enddo
!	  nullify(traverse%next_node)


	ALLOCATE(MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(nnk),
     +stat=error)
	if(error.ne.0) then
      write(911,*) "allocate P() in mucpath_hov_array vector, error"
	  pause
	endif
   
	! Copy contents from temp back to array 
	  ipath = 1
	  do while(tmpuepath(ipath).gt.0)
	  MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(ipath)
     +	   = tmpuepath(ipath)
        ipath = ipath + 1
	  enddo
        
	if(ipath-1 .ne.nnk) then
	 print *, 'Inconsistency exists between the numbers of nodes for
     +	  MUC paths'
	pause
	endif


! End of Modification


	  uepath_hov(i,j,t,nowpath) = NumMucPath_hov(i,j)
        uepolicy_hov(i,j,t,nowpath)%nodesum = tmpnodsum !record node sum for this new path
        uepolicy_hov(i,j,t,nowpath)%nodenumber = nnk
	 
	  else	! this path is found the grand path set
	   uepath_hov(i,j,t,nowpath) = iflag3
         uepolicy_hov(i,j,t,nowpath)%nodesum = 
     +        MucPathAtt_hov(i,j,iflag3)%node_sum !record node sum for this new path
         uepolicy_hov(i,j,t,nowpath)%nodenumber =
     +        MucPathAtt_hov(i,j,iflag3)%node_number 
	 endif

      ELSE
	 nowpath=NumUePath_hov(i,j,t)
	ENDIF
  	 
c --------------------------------
c --  Starting the assignment
c --------------------------------

      IF(iflag2.eq.0) then !new path found

       do kh = 1, nowpath
	 if (kh.ne.nowpath) then
	   aux(kh) = 0.0
           auxprob(kh) = 0.0     
       else
	   aux(kh) = real(uenxz_hov(i,j,t))  ! all trips go to the aux path of the new path
           auxprob(kh) = 1.0         
	 endif
  	 enddo
	 do mb = 1, nowpath
	  xn=(1.0-1.0/(iteration+1))*
     *  uepolicy_hov(i,j,t,mb)%NumOfVehicle
     *  + 1.0/(iteration+1)*aux(mb)
	  if(abs(xn-uepolicy_hov(i,j,t,mb)%NumOfVehicle).gt.muc_diff)
     *  TotalViolation = TotalViolation + 
     *  abs(xn-uepolicy_hov(i,j,t,mb)%NumOfVehicle)
	  uepolicy_hov(i,j,t,mb)%NumOfVehicle = xn

        newprob = (1.0-1.0/(iteration+1))*   
     *  uepolicy_hov(i,j,t,mb)%prob+1.0/(iteration+1)*auxprob(mb)
        uepolicy_hov(i,j,t,mb)%prob = newprob
	 enddo
	

      ELSE                 ! old path found
	

       do kh = 1, nowpath
	  if (kh.ne.iflag2) then
	   aux(kh) = 0.0
	   auxprob(kh) = 0.0
        else
	   aux(kh) = real(uenxz_hov(i,j,t))  ! all trips go to aux path of found path
           auxprob(kh) = 1.0    
	  endif
  	 enddo
	 do mb = 1, nowpath
	  xn=(1.0-1.0/(iteration+1))*
     *  uepolicy_hov(i,j,t,mb)%NumOfVehicle
     *  + 1.0/(iteration+1)*aux(mb)
	  if(abs(xn-uepolicy_hov(i,j,t,mb)%NumOfVehicle).gt.muc_diff)
     *  TotalViolation = TotalViolation + 
     *  abs(xn-uepolicy_hov(i,j,t,mb)%NumOfVehicle)
	  uepolicy_hov(i,j,t,mb)%NumOfVehicle = xn

         newprob = (1.0-1.0/(iteration+1))* 
     *  uepolicy_hov(i,j,t,mb)%prob+1.0/(iteration+1)*auxprob(mb)
        uepolicy_hov(i,j,t,mb)%prob = newprob
 	  enddo
	ENDIF

800   continue      

70	continue
c ---------------------------------------------------
c -----  calculate accumulated prob for each i,j,t,k
c ---------------------------------------------------

      do kk = 1, nowpath
       if(kk.eq.1) then  ! the first path
         ueaccuprob_hov(i,j,t,kk) = uepolicy_hov(i,j,t,kk)%prob
       else
         ueaccuprob_hov(i,j,t,kk) = ueaccuprob_hov(i,j,t,kk-1) +
     *   uepolicy_hov(i,j,t,kk)%prob
       endif
       if(kk.eq.nowpath) ueaccuprob_hov(i,j,t,kk) = 1.0
      enddo


1001    format(i6,f8.4,2i6)
1002    format(150i7)
200   continue
10    continue
100   continue
      
c ------------------------------------
c     reassign paths to UE vehicles
c     has been moved to get_uepath_hov
c ------------------------------------

	do t = 1, soint
	write(59,*) 'Time',t

	do j = 1, noof_master_destinations_original
	write(59,*) 'Destination',j


!      do i = 1,noofnodes_org
      do i = 1,nzones
c	write(59,*) '---------'

c ----------------------------------------------------
c -----  small test to see if the path is correct
c ----------------------------------------------------
 
      write(59,*) i,NumUePath_hov(i,j,t),uenxz_hov(i,j,t)
      do mk= 1, NumUePath_hov(i,j,t)
!      traverse=>MucPath_hov(i,j,uepath_hov(i,j,t,mk))
       ih=1
       testpath(:) = 0
!      do while (associated(traverse%next_node))
!       testpath(ih) = traverse%node
!       traverse=>traverse%next_node
!       if(ih.lt.maxnu_pa) then
!         ih=ih+1
!       else
!         print *, 'Eror in ueassign, path longer than maxnu_pa'
!         write(*,*) (testpath(mh),mh=1,maxnu_pa)
!         exit
!       endif
!      enddo


      do ih =1,MucPathAtt_Hov(i,j,uepath_hov(i,j,t,mk))%node_number

      testpath(ih)= MUCPath_Hov_Array(i,j,uepath_hov(i,j,t,mk))%P(ih)

        if(ih.gt.maxnu_pa) then
          print *, 'Eror in ueassign, path longer than maxnu_pa'
          write(*,*) (testpath(mh),mh=1,maxnu_pa)
          exit
        endif

       enddo

!End of modification

	ipathsize=MucPathAtt_Hov(i,j,uepath_hov(i,j,t,mk))%node_number


***************************
       do mm2 = 2, ipathsize-1
       if(testpath(mm2).gt.noofnodes_org.or.testpath(mm2).lt.1)then
       print *, 'error in testpath'
       endif
       enddo
******************************


!       write(59,1001) uepolicy_hov(i,j,t,mk)%NumOfVehicle,

 
       write(59,1001) uepolicy_hov(i,j,t,mk)%NumOfVehicle,
     *  uepolicy_hov(i,j,t,mk)%prob,ipathsize-2,nodenum(testpath(2))


!       write(59,1002) uepolicy_hov(i,j,t,mk)%nodenumber-1,! not printing centroid
!     *  nodenum(testpath(1:ih-2))

      write(59,1002) nodenum(testpath(2:ipathsize-1))! not printing centroid

      enddo

	enddo
	enddo
	enddo

      deallocate(aux,stat=error)
	  if(error.ne.0) then
	    print *,"deallocate aux error"
	    stop
	  endif
      deallocate(auxprob,stat=error)
          if(error.ne.0) then
            print *,"deallocate auxprob error"
            stop
          endif
	deallocate(testpath,stat=error)
	deallocate(tmpuepath,stat=error)


      close(59)
	return
	end
