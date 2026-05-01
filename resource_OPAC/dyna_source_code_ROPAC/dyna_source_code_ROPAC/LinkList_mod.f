      MODULE LinkList_mod
c	! Sept 2001 by Yi-Chang Chiu
c	! This module contains the data structure and methods for link manipulation in dynasmart
c	! The new data structure implementation intends to reduce both the memory useage and computational time
c	! The new implementation defines the physical links, entry link and waiting list for trip chain
c	! as a link list as TYPE Linkstruct
c	! The process of the link list is handled by individual pointer assciated with different methods
      TYPE linkstruct
      INTEGER::veh
      TYPE(linkstruct),pointer::next_veh
      END TYPE linkstruct
c	! --  Define the data structure for storing the attributes of each path in the Grand Path Set
c	! --  LinkVehList: link list keeps all the vehicles on the link
      TYPE(linkstruct),pointer::PTemp
      TYPE(linkstruct),pointer,dimension(:)::LinkVehList
      TYPE(linkstruct),pointer,dimension(:)::EntQueVehList
      TYPE(linkstruct),pointer,dimension(:)::TripChainList
      TYPE(linkstruct),pointer::p_mtxj_value
      TYPE(linkstruct),pointer::p_mtxj_insert,p_mtxj_remove
      TYPE(linkstruct),pointer::p_mtqj_insert,p_mtqj_InsFront,
     +	p_mtqj_remove,p_mtqj_value
	TYPE(linkstruct),pointer::p_TripChain_Remove,p_TripChain_insert
	contains
c	! This subroute is the method for inserting a node into the list LinkVehList
	SUBROUTINE mtxj_insert(ilink,VehID)
	INTEGER VehID
	p_mtxj_insert=>LinkVehList(ilink)
  	do while(p_mtxj_insert%veh.gt.0)
    	p_mtxj_insert=>p_mtxj_insert%next_veh
	if(p_mtxj_insert%veh.eq.VehID)then
	  print *, 'mtxj_insert error'
    	endif
  	enddo
  	p_mtxj_insert%veh=VehID
c	if(associated(p_mtxj_insert%next_veh))
c	+deallocate(p_mtxj_insert%next_veh)
  	allocate(p_mtxj_insert%next_veh)
  	p_mtxj_insert=>p_mtxj_insert%next_veh
  	p_mtxj_insert%veh=0
  	nullify(p_mtxj_insert%next_veh)
c  	deallocate(p_mtxj_insert%next_veh)
	END SUBROUTINE
c --
	SUBROUTINE mtxj_remove(ilink,VehID)
c	! This SUBROUTINE removes the VehID out of the link list of ilink
	 TYPE(linkstruct),pointer::passtp
	 INTEGER VehID,FindFlag
	 allocate(passtp)  
	 p_mtxj_remove=>LinkVehList(ilink)
	 if(p_mtxj_remove%veh.eq.VehID)then !if the first nodes is to be removed
      	passtp=p_mtxj_remove
      	p_mtxj_remove=>p_mtxj_remove%next_veh
      	LinkVehList(ilink)=p_mtxj_remove
	if(.not.associated(p_mtxj_remove%next_veh))then
        allocate(p_mtxj_remove%next_veh)
        p_mtxj_remove=>p_mtxj_remove%next_veh
        p_mtxj_remove%veh=0
        nullify(p_mtxj_remove%next_veh)
	  endif
 	else
    	do while(associated(p_mtxj_remove%next_veh))
      	passtp=p_mtxj_remove
	p_mtxj_remove=>p_mtxj_remove%next_veh
      	FindFlag=0
      	if(p_mtxj_remove%veh.eq.VehID)then
	    FindFlag=1
	    exit
	  endif
    	enddo
    	if(FindFlag.lt.1)then
      	print *, 'mtxj_remove error'
    	else
       	passtp%next_veh=p_mtxj_remove%next_veh
	   if(associated(p_mtxj_remove%next_veh)) 
     +	p_mtxj_remove=>p_mtxj_remove%next_veh
	     if(.not.associated(p_mtxj_remove%next_veh))then
	     allocate(p_mtxj_remove%next_veh)
           p_mtxj_remove=>p_mtxj_remove%next_veh
           p_mtxj_remove%veh=0
           nullify(p_mtxj_remove%next_veh)
	     endif   
	endif
 	endif
	deallocate(passtp)
	END SUBROUTINE
c	!--------------MTQJ--------------------
	SUBROUTINE mtqj_insert(ilink,VehID)
c	! This subroutine inserts the VehID into the entry queue of ilink
	INTEGER VehID
  	p_mtqj_insert%veh=VehID
  	if(.not.associated(p_mtqj_insert%next_veh))then
    	allocate(p_mtqj_insert%next_veh)
    	p_mtqj_insert=>p_mtqj_insert%next_veh
    	p_mtqj_insert%veh=0
    	nullify(p_mtqj_insert%next_veh)
  	endif
	END SUBROUTINE
c --
	SUBROUTINE mtqj_InsFront(ilink,VehID)
c	! This subroutine insert the VehID at the front of the entry queue of link ilink
c	! this is needed for Trip Chain when the vehicle finsihed the activity
c	! it is inserted at the beginning of the list
	TYPE(linkstruct),pointer::passt2
	TYPE(linkstruct),pointer::passt4
	INTEGER VehID
	p_mtqj_InsFront=>EntQueVehList(ilink) ! Intert into entry queue
  	allocate(passt2)
  	passt2=p_mtqj_InsFront
  	allocate(passt4)
  	EntQueVehList(ilink)=passt4 ! give EntQueVehList a new pointer
  	p_mtqj_InsFront=>EntQueVehList(ilink) 
  	p_mtqj_InsFront%veh=VehID
  	allocate(p_mtqj_InsFront%next_veh)
  	p_mtqj_InsFront%next_veh=passt2
  	deallocate(passt2)
  	deallocate(passt4)
	END SUBROUTINE
c --
	SUBROUTINE mtqj_remove(ilink,VehID)
c	! This subroutine removes the VehID out of the list of link ilink
 	TYPE(linkstruct),pointer::pass2t
 	INTEGER VehID,FindFlag
 	allocate(pass2t)  
 	p_mtqj_remove=>EntQueVehList(ilink)
    	pass2t=p_mtqj_remove
    	p_mtqj_remove=>p_mtqj_remove%next_veh
    	EntQueVehList(ilink)=p_mtqj_remove
 	deallocate(pass2t)
	END SUBROUTINE
c --
	INTEGER FUNCTION mtqj_value(ilink)
c --
 	INTEGER ilink
 	mtqj_value=p_mtqj_value%veh
	END FUNCTION
c	! The followins are for Trip Chain
	SUBROUTINE TripChain_insert(ilink,VehID)
c	! This subroutine insert the VehID into the list of Trip Chain
	INTEGER VehID
	p_TripChain_insert=>TripChainList(ilink)
  	do while(associated(p_TripChain_insert%next_veh))
    	p_TripChain_insert=>p_TripChain_insert%next_veh
	if(p_TripChain_insert%veh.eq.VehID)then
	  print *, 'TripChain_insert error'
    	endif
  	enddo
  	p_TripChain_insert%veh=VehID
  	allocate(p_TripChain_insert%next_veh)
  	p_TripChain_insert=>p_TripChain_insert%next_veh
  	p_TripChain_insert%veh=0
  	nullify(p_TripChain_insert%next_veh)
	END SUBROUTINE
c --
	SUBROUTINE TripChain_remove(ilink,VehID)
c	! This subroutine removes the VehID out of the Trip Chain list of link ilink
 	TYPE(linkstruct),pointer::pass2t
 	INTEGER VehID,FindFlag
 	allocate(pass2t)  
 	p_TripChain_Remove=>TripChainList(ilink)
 	if(p_TripChain_remove%veh.eq.VehID)then !if the first nodes is to be removed
    	pass2t=p_TripChain_remove
    	p_TripChain_remove=>p_TripChain_remove%next_veh
    	TripChainList(ilink)=p_TripChain_remove
    	allocate(p_TripChain_remove%next_veh)
    	p_TripChain_remove=>p_TripChain_remove%next_veh
    	p_TripChain_remove%veh=0
    	nullify(p_TripChain_remove%next_veh)
 	else ! search to find the vehicle
    	do while(associated(p_TripChain_remove%next_veh))
      	pass2t=p_TripChain_remove
	p_TripChain_remove=>p_TripChain_remove%next_veh
      	FindFlag=0
      	if(p_TripChain_remove%veh.eq.VehID)then
	    findFlag=1
	    exit
	  endif
    	enddo
    	if(FindFlag.lt.1)then
      	print *, 'TripChain_remove error'
    	else ! vehicle found
	   if(.not.associated(p_TripChain_remove%next_veh))then ! if this vehicle is at the end of the list
	 allocate(p_TripChain_remove%next_veh)
         p_TripChain_remove=>p_TripChain_remove%next_veh
         p_TripChain_remove%veh=0
         nullify(p_TripChain_remove%next_veh)
           endif
	pass2t%next_veh=p_TripChain_remove%next_veh ! point pass2t to the next vehicle
c	!	     p_TripChain_remove=>p_TripChain_remove%next_veh
c	!       endif
    	endif
 	endif
 	deallocate(pass2t)
	END SUBROUTINE
	END MODULE 
